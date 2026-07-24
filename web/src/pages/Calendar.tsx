// Calendar heatmap — availability density across the week from slot_proposals /
// busy_blocks. TODO: fetch via api("/api/scheduling/...") once the router lands.
export function Calendar() {
  return (
    <section>
      <h2>Calendar</h2>
      <p>Conflict-free slot heatmap. Wire to the scheduling API when it exists.</p>
    </section>
  );
}
