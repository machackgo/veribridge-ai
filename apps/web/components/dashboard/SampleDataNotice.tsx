/**
 * Unmissable banner for dashboard routes whose body is still illustrative
 * sample content rather than the signed-in user's own data.
 *
 * Production audit 2026-07-21 found eight authenticated routes rendering
 * `data/mock.ts` (and inline literals) as if they were the viewer's own
 * analysis — fabricated skill gaps, another person's name and "verified"
 * .edu address, asserted immigration status, and privacy toggles that only
 * set local state. Presenting any of that as the user's own data is a
 * correctness defect, not a cosmetic one, so every such route must say so
 * before the content is read.
 *
 * Remove the banner from a route only when that route is genuinely wired to
 * the signed-in user's data.
 */
export function SampleDataNotice({ controlsInert = false }: { controlsInert?: boolean }) {
  return (
    <div
      role="alert"
      data-testid="sample-data-notice"
      style={{
        border: "2px solid #b45309",
        background: "#fffbeb",
        color: "#7c2d12",
        borderRadius: 10,
        padding: "12px 14px",
        marginBottom: 16,
        fontSize: 13,
        lineHeight: 1.5,
      }}
    >
      <strong style={{ display: "block", fontSize: 14, marginBottom: 4 }}>
        Sample preview — this is not your data
      </strong>
      Every name, number, and percentage below is illustrative placeholder content shown to all
      accounts. It is not derived from your proofs, your evidence, or your account.
      {controlsInert ? (
        <>
          {" "}
          <strong>The controls on this page are not connected</strong> — changing them does not
          change what anyone can see. Your real, enforced sharing settings live in your Work
          Passport and its publish controls.
        </>
      ) : null}
    </div>
  );
}
