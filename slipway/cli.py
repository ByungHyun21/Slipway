"""`slip` command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import forge, gates, model, previews, serve, state, store


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="slip", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("init", help="create a forge project")
    a.add_argument("path", nargs="?", default=".")
    a.set_defaults(func=cmd_init)

    a = sub.add_parser("brief", help="register a new asset in state `brief`")
    a.add_argument("id")
    a.add_argument("--type", required=True, choices=model.TYPES)
    a.add_argument("--scene", help="scene_ref back-pointer, e.g. canon/story/ch03.md#L12")
    a.add_argument("--character", help="canon back-pointer, e.g. canon/characters/hero.yaml")
    a.add_argument("--note")
    a.set_defaults(func=cmd_brief)

    a = sub.add_parser("add", help="add a revision: copy generations into staging, run gates")
    a.add_argument("id")
    a.add_argument("files", nargs="+", type=Path)
    a.add_argument("--backend", required=True,
                   help="generator backend: comfyui | wangp | yue | cosyvoice | stable-audio | llm")
    a.add_argument("--param", action="append", default=[], metavar="K=V",
                   help="generation parameter (repeatable)")
    a.set_defaults(func=cmd_add)

    a = sub.add_parser("gate", help="re-run gates on a revision")
    a.add_argument("id")
    a.add_argument("--rev", type=int)
    a.set_defaults(func=cmd_gate)

    a = sub.add_parser("approve", help="human approval: copy a gated revision to approved/")
    a.add_argument("id")
    a.add_argument("--rev", type=int)
    a.set_defaults(func=cmd_approve)

    a = sub.add_parser("list", help="list assets")
    a.add_argument("--status", choices=state.STATUSES)
    a.set_defaults(func=cmd_list)

    a = sub.add_parser("show", help="show one asset with revisions and gate results")
    a.add_argument("id")
    a.set_defaults(func=cmd_show)

    a = sub.add_parser("export", help="launch: copy an approved revision out of the forge")
    a.add_argument("id")
    a.add_argument("--rev", type=int)
    a.add_argument("--to", required=True, type=Path, help="target directory (e.g. ../MyGame/assets/generated)")
    a.set_defaults(func=cmd_export)

    a = sub.add_parser("serve", help="serve the approved catalog for download")
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--port", type=int, default=8321)
    a.set_defaults(func=cmd_serve)

    try:
        return main_dispatch(p, argv)
    except model.RegistryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def main_dispatch(p: argparse.ArgumentParser, argv) -> int:
    args = p.parse_args(argv)
    return args.func(args)


def cmd_init(args) -> int:
    root = forge.init(args.path)
    print(f"forge initialized at {root}")
    return 0


def cmd_brief(args) -> int:
    root = forge.require()
    model.create(root, args.id, args.type, scene_ref=args.scene,
                 character=args.character, note=args.note)
    print(f"brief: {args.id} ({args.type})")
    return 0


def cmd_add(args) -> int:
    root = forge.require()
    asset = model.load(root, args.id)
    rev = model.next_rev(asset)
    files = store.ingest(root, args.id, rev, args.files)
    params = {}
    for kv in args.param:
        if "=" not in kv:
            raise SystemExit(f"error: --param expects K=V, got {kv!r}")
        k, v = kv.split("=", 1)
        params[k] = _coerce(v)
    rev_data = {"rev": rev, "backend": args.backend, "created": store.now(),
                "params": params, "files": files, "gates": {}}
    asset["revisions"].append(rev_data)
    state.advance(asset, "generated")
    out = gates.run_gates(root, asset, rev_data)
    _apply_gate_result(asset, rev_data, out)
    model.save(root, asset)
    print(f"{args.id} rev {rev}: staged {len(files)} file(s) -> {asset['status']}")
    return _report_gates(args.id, rev, out)


def cmd_gate(args) -> int:
    root = forge.require()
    asset = model.load(root, args.id)
    rev_data = model.find_revision(asset, args.rev)
    out = gates.run_gates(root, asset, rev_data)
    _apply_gate_result(asset, rev_data, out)
    model.save(root, asset)
    return _report_gates(args.id, rev_data["rev"], out)


def _apply_gate_result(asset: dict, rev_data: dict, out: dict) -> None:
    rev_data["gates"] = out["gates"]
    rev_data["gate_reasons"] = out["reasons"]
    rev_data["gated_at"] = store.now()
    if out["passed"]:
        state.advance(asset, "gated")
    else:
        state.bounce(asset)


def _report_gates(asset_id: str, rev: int, out: dict) -> int:
    status = "PASS" if out["passed"] else "FAIL"
    print(f"rev {rev} gates: {status}")
    for gate, verdict in out["gates"].items():
        print(f"  {gate}: {verdict}")
    for reason in out["reasons"]:
        print(f"  ! {reason}", file=sys.stderr)
    if not out["passed"]:
        print(f"  bounced back into the generation loop", file=sys.stderr)
    return 0 if out["passed"] else 1


def cmd_approve(args) -> int:
    root = forge.require()
    asset = model.load(root, args.id)
    rev_data = model.find_revision(asset, args.rev)
    if not rev_data.get("gates") or any(v != "pass" for v in rev_data["gates"].values()):
        print(f"error: rev {rev_data['rev']} has not passed its gates; run `slip gate {args.id}`",
              file=sys.stderr)
        return 1
    store.approve_copy(root, args.id, rev_data["rev"], rev_data["files"])
    rev_data["approved_at"] = store.now()
    state.advance(asset, "approved")
    model.save(root, asset)
    made = previews.derive(root, args.id, rev_data["rev"], rev_data["files"])
    print(f"approved: {args.id} rev {rev_data['rev']}"
          + (f" + {len(made)} poster(s)" if made else ""))
    return 0


def cmd_list(args) -> int:
    root = forge.require()
    rows = []
    for asset in model.list_assets(root):
        if args.status and asset["status"] != args.status:
            continue
        rev = model.latest_revision(asset)
        rev_s = f"{rev['rev']}@{rev['backend']}" if rev else "-"
        gates_s = ("gates:" + ",".join(sorted(set(rev["gates"].values())))) if rev and rev.get("gates") else ""
        rows.append((asset["id"], asset["type"], asset["status"], rev_s, gates_s))
    if not rows:
        print("no assets")
        return 0
    widths = [max(len(r[i]) for r in rows + [("ID", "TYPE", "STATUS", "REV", "")]) for i in range(5)]
    print("  ".join(h.ljust(w) for h, w in zip(("ID", "TYPE", "STATUS", "REV", "GATES"), widths)))
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)))
    return 0


def cmd_show(args) -> int:
    root = forge.require()
    asset = model.load(root, args.id)
    print(f"{asset['id']}  type={asset['type']}  status={asset['status']}")
    for k in ("scene_ref", "character", "note"):
        if asset.get(k):
            print(f"  {k}: {asset[k]}")
    for r in asset["revisions"]:
        mark = " *".join(x for x in ("gated" if r.get("gated_at") else "",
                                     "approved" if r.get("approved_at") else "",
                                     "exported" if r.get("exported_at") else "") if x)
        print(f"  rev {r['rev']}  backend={r['backend']}  created={r['created']}{' ' + mark if mark else ''}")
        for f in r["files"]:
            print(f"    {f['name']}  {f['bytes']}B  {f['checksum'][:26]}..")
        for g, v in (r.get("gates") or {}).items():
            print(f"    gate {g}: {v}")
        for reason in r.get("gate_reasons", []):
            print(f"    ! {reason}")
    if asset.get("exports"):
        print(f"  exports: {asset['exports']}")
    return 0


def cmd_export(args) -> int:
    root = forge.require()
    asset = model.load(root, args.id)
    rev_data = model.find_revision(asset, args.rev)
    if not rev_data.get("approved_at"):
        print(f"error: rev {rev_data['rev']} is not approved; only human-picked artifacts launch",
              file=sys.stderr)
        return 1
    target = args.to if args.to.is_absolute() else Path.cwd() / args.to
    dst = store.export_copy(root, args.id, rev_data["rev"], rev_data["files"], target)
    rev_data["exported_at"] = store.now()
    asset.setdefault("exports", {})["local"] = _rel(root, target)
    state.advance(asset, "exported")
    model.save(root, asset)
    print(f"exported: {args.id} rev {rev_data['rev']} -> {dst}")
    return 0


def cmd_serve(args) -> int:
    root = forge.require()
    print(f"slipway serving {root} on http://{args.host}:{args.port} (approved artifacts only; Ctrl-C to stop)")
    serve.serve(root, args.host, args.port)
    return 0


def _coerce(v: str):
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _rel(root: Path, target: Path) -> str:
    try:
        return str(target.resolve().relative_to(root))
    except ValueError:
        return str(target.resolve())
