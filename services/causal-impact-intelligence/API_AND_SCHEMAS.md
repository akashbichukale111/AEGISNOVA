# API v1 (127.0.0.1, JSON). Errors: `{"error": CODE, "message": ...}` (400 input, 404, 413, 500 generic - no internals/secrets)
GET `/api/v1/health` | POST `/demo` | POST `/import` `{files:[{name,content}], incident?}` | POST `/incident` | GET `/graph` | GET `/node/<id>` |
POST `/rca` `{incident?}` | POST `/impact` `{node_id,max_depth?,max_nodes?,environment?,node_types?,edge_types?,exclude_dev?}` | POST `/analyze` `{node_id?}` |
POST `/counterfactual` and `/compare` `{scenario:{type,node_id|edge_id,new_version?,timestamp?}}` | POST `/export` `{format:"json"|"markdown"}`.
Codes: NO_INPUT, NO_GRAPH, NO_INCIDENT, UNSUPPORTED_FORMAT, MALFORMED_INPUT, INPUT_TOO_LARGE, MALFORMED_JSON, BAD_REQUEST, NODE_NOT_FOUND.
Incident: `{incident_id?, timestamp(ISO), affected_component, window_hours?, symptoms[], events:[{event_id,timestamp,component,type:change|deploy|health,description}], advisories:[{id,component,affected_versions?}]}`.
Analysis result keys: schema_version, analysis_id, graph_hash, incident, impact_target, root_cause, impact, blast_radius, graph_coverage, known, inferred, unknown, warnings, recommended_next_steps, limitations, generated_at.
Example: `curl -XPOST localhost:8765/api/v1/impact -d '{"node_id":"svc:auth"}'`.
