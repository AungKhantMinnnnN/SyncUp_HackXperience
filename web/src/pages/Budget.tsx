// Budget burn-down — allocation vs. drafted/spent against the semester cap.
// Money is strings on the wire; parse with Number() only for rendering, never for math.
// TODO: fetch via api("/api/finance/...") once the router lands.
export function Budget() {
  return (
    <section>
      <h2>Budget</h2>
      <p>Allocation burn-down against the semester cap. Wire to the finance API when it exists.</p>
    </section>
  );
}
