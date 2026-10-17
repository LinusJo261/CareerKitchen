import { defineRailway, project, service } from "railway/iac";

// This backend repository manages only these two services. Supabase remains external.
export const partial = "career-kitchen-backend";

export default defineRailway((context) => {
  const api = service("career-kitchen-api", {
    start: 'sh -c "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"',
    preDeploy: "python -m app.check_schema",
    healthcheck: "/v1/health",
    healthcheckTimeout: 30,
    replicas: 1,
  });
  const worker = service("career-kitchen-worker", {
    start: "python -m app.workers.runner",
    replicas: 1,
  });
  return project(context.projectName || "Career Kitchen", { resources: [api, worker] });
});

