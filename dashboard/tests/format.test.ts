import { describe, expect, it } from "vitest";
import { niceCeil } from "../src/components/BarChart";
import { describeAudit, fmtEur, madridDay, madridMidnightISO, timeAgo } from "../src/lib/format";
import { translateError } from "../src/lib/useData";

describe("formato", () => {
  it("euros en formato español", () => {
    expect(fmtEur(1234.5).replace(/\s/g, " ")).toBe("1234,50 €");
    expect(fmtEur(null)).toBe("—");
  });
  it("tiempo relativo", () => {
    const now = new Date("2026-11-08T12:00:00Z");
    expect(timeAgo("2026-11-08T11:59:30Z", now)).toBe("hace un momento");
    expect(timeAgo("2026-11-08T09:00:00Z", now)).toBe("hace 3 h");
    expect(timeAgo("2026-11-07T12:00:00Z", now)).toBe("hace 1 día");
  });
  it("día y medianoche en Madrid con horario de verano", () => {
    expect(madridDay(new Date("2026-11-08T23:30:00Z"))).toBe("2026-11-09");
    expect(madridMidnightISO(new Date("2026-11-08T12:00:00Z"))).toBe("2026-11-08T00:00:00+01:00");
    expect(madridMidnightISO(new Date("2026-07-08T12:00:00Z"))).toBe("2026-07-08T00:00:00+02:00");
  });
  it("historial legible", () => {
    expect(describeAudit("proposal.approved")).toBe("Propuesta aprobada");
    expect(describeAudit("tasks.update")).toBe("tasks: modificado");
  });
  it("errores traducidos", () => {
    expect(translateError("permission denied for table proposals")).toBe("No tienes permiso para esta acción.");
  });
  it("escala de la gráfica", () => {
    expect(niceCeil(87)).toBe(100);
    expect(niceCeil(0.43)).toBe(0.5);
    expect(niceCeil(0)).toBe(1);
  });
});
