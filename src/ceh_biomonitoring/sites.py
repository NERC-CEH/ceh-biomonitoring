"""cehbio deployments: see your deployments and ask UKCEH for new ones.

A deployment is one device (camera, trap or recorder) at one site for one survey period. Uploads always
go to a deployment, so it has to exist (and be active) before you upload.

  cehbio deployments list                 the deployments you can see, and whether each is active
  cehbio deployments request              ask for a new one (asks step by step)

A request is 'pending' until UKCEH checks and approves it; then it becomes 'active' and appears in
cehbio upload.
"""
from __future__ import annotations

import getpass
import os
import re

from .upload import DEFAULT_URL, UploadService, _ask, _choose, saved_login


def _service(settings) -> UploadService:
    saved = saved_login(settings)
    url = saved.get("UPLOAD_URL") or settings.get("upload.url") or DEFAULT_URL
    user = os.environ.get("CEHBIO_UPLOAD_USER") or saved.get("UKCEH_username") or _ask("Upload service username")
    pw = (os.environ.get("CEHBIO_UPLOAD_PASSWORD") or saved.get("UKCEH_password")
          or getpass.getpass("Upload service password (hidden): "))
    return UploadService(url, user, pw)


def show(args, settings) -> None:
    deps = _service(settings).deployments()
    if args.country:
        deps = [d for d in deps if args.country.lower() in d.get("country", "").lower()]
    if not args.all:
        deps = [d for d in deps if d.get("status") in ("active", "pending")]
    if not deps:
        print("No deployments found." + ("" if args.all else " (Add --all to include inactive ones.)"))
        return
    print(f"{'ID':10s} {'status':8s} {'country':16s} {'site':28s} {'device':16s} {'dates'}")
    for d in sorted(deps, key=lambda d: (d.get("country", ""), d.get("location_name", ""))):
        dates = " to ".join(x for x in (d.get("start_date"), d.get("end_date")) if x)
        print(f"{d['deployment_id']:10s} {d.get('status', ''):8s} {d.get('country', '')[:16]:16s} "
              f"{d.get('location_name', '')[:28]:28s} {d.get('camera_id', '')[:16]:16s} {dates}")
    print("\nOnly 'active' deployments can be uploaded to. 'pending' ones are waiting for UKCEH to check them.")


def _number(prompt: str, low: float, high: float, given=None) -> str:
    while True:
        v = str(given) if given is not None else _ask(prompt)
        try:
            if low <= float(v) <= high:
                return v
        except ValueError:
            pass
        if given is not None:
            raise SystemExit(f"{prompt}: must be a number between {low} and {high}")
        print(f"Please type a number between {low} and {high}, e.g. 51.6")


def _date(prompt: str, given=None, required=False) -> str:
    while True:
        v = given if given is not None else _ask(prompt + (" (YYYY-MM-DD)" if required else " (YYYY-MM-DD, or leave empty)"))
        if (not v and not required) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", v or ""):
            return v or ""
        if given is not None:
            raise SystemExit(f"{prompt}: use the form 2026-05-01")
        print("Please use the form 2026-05-01")


def request(args, settings) -> None:
    svc = _service(settings)
    deps = svc.deployments()
    countries = sorted({d["country"] for d in deps if d.get("country")})
    print("Ask UKCEH for a new deployment: one device at one site for one survey period.\n")
    name = args.name or _ask("Your full name")
    country = _choose("Country:", countries, args.country)
    site = args.site or _ask("Site name (short and clear, e.g. 'Wytham Woods 1')")
    print("Where exactly is the device? Decimal degrees, e.g. 51.7714 and -1.3389 (copy from a map app).")
    lat = _number("Latitude", -90, 90, args.lat)
    lon = _number("Longitude", -180, 180, args.lon)
    device_type = args.device_type or _choose("Device type:", ["AMI trap", "LepiSense / AMI-mini", "AudioMoth",
                                                               "Song Meter", "Insect Detect", "Other"])
    camera_id = args.device_id or _ask("Device ID or serial number (as written on the device or in its file names)")
    start = _date("First day of recording", args.start, required=True)
    end = _date("Last day of recording", args.end if (args.end is not None or not args.yes) else "")
    if args.notes is not None or args.yes:
        notes = args.notes or ""                   # unattended: optional details are left empty
    else:
        notes = _ask("Anything else UKCEH should know (or leave empty)")
    print(f"\n  {country} / {site} ({lat}, {lon})\n  {device_type} {camera_id}, from {start}"
          f"{' to ' + end if end else ''}\n  requested by {name}")
    if not args.yes and not _ask("\nSend this request? (yes/no)", "no").lower().startswith("y"):
        print("Not sent.")
        return
    fields = {"country": country, "location_name": site, "lat": lat, "lon": lon, "camera_id": camera_id,
              "requested_by": name, "device_type": device_type, "start_date": start, "end_date": end, "notes": notes}
    try:
        r = svc._post("request-deployment/", fields)
    except RuntimeError as e:
        msg = str(e)
        if "HTTP 422" in msg:
            import json
            try:
                msg = json.loads(msg.split(": ", 1)[1]).get("message", msg)
            except (ValueError, IndexError):
                pass
            raise SystemExit(f"UKCEH's service could not accept this request:\n  {msg}")
        raise
    print(f"\nSent. Your deployment ID is {r['deployment_id']} (pending).\n"
          f"UKCEH will check it and make it active; you'll then see it in `cehbio upload`.\n"
          f"Check with: cehbio deployments list")


def add_command(sub, common) -> None:
    d = sub.add_parser("deployments", parents=[common], help="see your deployments, or ask for a new one",
                       description=__doc__, formatter_class=__import__("argparse").RawDescriptionHelpFormatter)
    ds = d.add_subparsers(dest="dep_cmd", required=True)
    ls = ds.add_parser("list", help="the deployments you can see")
    ls.add_argument("--country", help="only this country")
    ls.add_argument("--all", action="store_true", help="include inactive and rejected ones")
    rq = ds.add_parser("request", help="ask UKCEH for a new deployment (asks step by step)")
    for opt, h in (("--name", "your full name"), ("--country", "country, as listed"), ("--site", "site name"),
                   ("--lat", "latitude, decimal degrees"), ("--lon", "longitude, decimal degrees"),
                   ("--device-type", "e.g. AMI trap, LepiSense / AMI-mini, AudioMoth"),
                   ("--device-id", "the device's ID or serial number"), ("--start", "first day, YYYY-MM-DD"),
                   ("--end", "last day, YYYY-MM-DD"), ("--notes", "anything else UKCEH should know")):
        rq.add_argument(opt, help=h)
    rq.add_argument("--yes", action="store_true", help="don't ask for confirmation")

    def run(args):
        from .settings import Settings
        s = Settings.load(profile=getattr(args, "profile", None))
        (show if args.dep_cmd == "list" else request)(args, s)
    d.set_defaults(func=run)
