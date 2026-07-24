// Resource timeline — reservations per resource over time, exclusive clashes flagged.
// TODO: fetch via api("/api/resources/...") once the router lands.
export function Resources() {
  return (
    <section>
      <h2>Resources</h2>
      <p>Reservation timeline with conflict highlights. Wire to the resources API when it exists.</p>
    </section>
  );
}
