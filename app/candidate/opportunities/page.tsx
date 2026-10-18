import { TodaysMenu } from "@/components/candidate/todays-menu";
import { SampleCatalog } from "@/components/sample-catalog";

export const metadata = { title: "Today's Menu" };

export default function Page() {
  return (
    <>
      <TodaysMenu />
      <SampleCatalog />
    </>
  );
}
