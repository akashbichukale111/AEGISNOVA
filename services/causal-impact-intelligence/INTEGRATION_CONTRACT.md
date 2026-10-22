# Future integration contract (NOT implemented / NOT connected)
- Output: analysis result JSON (schema_version 1.0) exposing `impact.affected[].path` and `unknown`/`limitations` for Repair Assurance (WS04) and NightShift SDE as read-only inputs.
- Input from Evidence Intelligence (WS02): must be adapted to the incident `events`/`advisories` schema or a service-map JSON via a documented adapter; nothing is assumed to exist today.
- Risk engine may consume `blast_radius.level` + `dimensions` as a policy indicator only.
- UNWIND Governance Core keeps all approval authority; this module never approves, repairs, merges or deploys.
- Versioning: bump `schema_version` on breaking changes; additive fields are non-breaking.
