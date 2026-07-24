export const fmtTime = (iso: string, tz: string) =>
  new Date(iso).toLocaleString("en-SG", {
    timeZone: tz,
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

export const money = (s: string | number) =>
  Number(s).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export const ms = (iso: string) => new Date(iso).getTime();

export const DAY = 864e5;
