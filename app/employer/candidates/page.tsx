import { PassBoard } from "@/components/pass/pass-board";
import { SampleCatalog } from "@/components/sample-catalog";

export const metadata = { title: "The Pass" };

export default function Page() {
  return (
    <>
      <PassBoard />
      <SampleCatalog initialKind="applicants" />
    </>
  );
}
