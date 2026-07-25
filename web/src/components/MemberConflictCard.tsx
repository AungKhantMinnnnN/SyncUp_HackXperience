// Interactive resolver for a member double-booking: an AI recommendation on request,
// plus one-click actions that actually remove the shared members from one event.
import { useState } from "react";
import { recommendMemberResolution, removeAttendees, rescheduleEvent } from "../api/scheduling";
import { MemberList } from "./MemberName";

export type ConflictGroup = {
  a: string;
  aId: string;
  b: string;
  bId: string;
  members: { id: string; name: string }[];
};

export function MemberConflictCard({
  group,
  roleByName,
  onResolved,
}: {
  group: ConflictGroup;
  roleByName: Record<string, string>;
  onResolved: () => void;
}) {
  const [rec, setRec] = useState<string | null>(null);
  const [busy, setBusy] = useState<null | "rec" | "rm-a" | "rm-b" | "mv-a" | "mv-b">(null);
  const [err, setErr] = useState<string | null>(null);
  const names = group.members.map((m) => m.name);
  const ids = group.members.map((m) => m.id);

  async function suggest() {
    setBusy("rec");
    setErr(null);
    try {
      const { recommendation } = await recommendMemberResolution(group.a, group.b, names);
      setRec(recommendation);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function removeFrom(which: "a" | "b") {
    setBusy(which === "a" ? "rm-a" : "rm-b");
    setErr(null);
    try {
      await removeAttendees(which === "a" ? group.aId : group.bId, ids);
      onResolved();
    } catch (e) {
      setErr((e as Error).message);
      setBusy(null);
    }
  }

  async function reschedule(which: "a" | "b") {
    setBusy(which === "a" ? "mv-a" : "mv-b");
    setErr(null);
    try {
      await rescheduleEvent(which === "a" ? group.aId : group.bId);
      onResolved();
    } catch (e) {
      setErr((e as Error).message);
      setBusy(null);
    }
  }

  return (
    <div className="callout">
      <div className="tag">Member conflict caught</div>
      <h3>
        {group.members.length} {group.members.length === 1 ? "member" : "members"} double-booked
      </h3>
      <p>
        <span className="vs">{group.a}</span> overlaps <span className="vs">{group.b}</span> —{" "}
        <MemberList names={names} roleByName={roleByName} /> can't be in both.
      </p>

      {rec && (
        <p style={{ marginTop: 10, paddingLeft: 12, borderLeft: "2px solid var(--ok)" }}>
          <strong className="tag" style={{ color: "var(--ok)" }}>AI recommends</strong>
          <br />
          {rec}
        </p>
      )}
      {err && <p className="err">{err}</p>}

      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <button className="btn" onClick={suggest} disabled={busy !== null}>
          {busy === "rec" ? "Thinking…" : rec ? "Ask again" : "Ask AI how to fix"}
        </button>
        <button className="btn primary" onClick={() => reschedule("a")} disabled={busy !== null}>
          {busy === "mv-a" ? "Rescheduling…" : `Reschedule ${group.a}`}
        </button>
        <button className="btn primary" onClick={() => reschedule("b")} disabled={busy !== null}>
          {busy === "mv-b" ? "Rescheduling…" : `Reschedule ${group.b}`}
        </button>
        <button className="btn" onClick={() => removeFrom("a")} disabled={busy !== null}>
          {busy === "rm-a" ? "Removing…" : `Drop members from ${group.a}`}
        </button>
        <button className="btn" onClick={() => removeFrom("b")} disabled={busy !== null}>
          {busy === "rm-b" ? "Removing…" : `Drop members from ${group.b}`}
        </button>
      </div>
    </div>
  );
}
