// One place that decides how a member reads in the UI: officers (president / treasurer
// / exec) get a bold name + role badge; regular members stay plain.
export const OFFICER_ROLES = new Set(["president", "treasurer", "exec"]);
export const isOfficer = (role?: string) => role != null && OFFICER_ROLES.has(role);

export function MemberName({ name, role }: { name: string; role?: string }) {
  const officer = isOfficer(role);
  return (
    <span className={officer ? "mname officer" : "mname"}>
      {name}
      {officer && <span className="role-badge">{role}</span>}
    </span>
  );
}

// Comma-separated list of members, each rendered with its role treatment.
export function MemberList({
  names,
  roleByName,
}: {
  names: string[];
  roleByName: Record<string, string>;
}) {
  return (
    <>
      {names.map((n, i) => (
        <span key={n}>
          {i > 0 && ", "}
          <MemberName name={n} role={roleByName[n]} />
        </span>
      ))}
    </>
  );
}
