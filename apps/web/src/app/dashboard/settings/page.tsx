import { StudentSettings } from "../../../../components/dashboard/StudentViews";
import { SampleDataNotice } from "../../../../components/dashboard/SampleDataNotice";

export default function Page() {
  return (
    <>
      <SampleDataNotice controlsInert />
      <StudentSettings />
    </>
  );
}
