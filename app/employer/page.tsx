import { Dashboard } from "@/components/workspace/dashboard";
import { SampleCatalog } from "@/components/sample-catalog";

export default function Page() {
  return (
    <>
      <Dashboard role="employer" />
      <SampleCatalog initialKind="applicants" />
    </>
  );
}
