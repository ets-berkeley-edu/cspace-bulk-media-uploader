import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import DateInput from "../components/DateInput.vue";
import { describeDate } from "../lib/dates";

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe("structured dates (design: Structured dates)", () => {
  it("describes the parsed earliest and latest dates", () => {
    expect(describeDate({ dateEarliestSingleYear: "1920", dateEarliestSingleMonth: "1", dateEarliestSingleDay: "1",
      dateLatestYear: "1929", dateLatestMonth: "12", dateLatestDay: "31" })).toBe("Earliest 1920-01-01 · latest 1929-12-31");
    expect(describeDate({ dateEarliestSingleYear: "1911", dateEarliestSingleMonth: "3", dateEarliestSingleDay: "3",
      dateLatestYear: "1911", dateLatestMonth: "3", dateLatestDay: "3" })).toBe("Earliest and latest 1911-03-03");
    expect(describeDate({ dateEarliestSingleYear: "1850", dateEarliestSingleCertainty:
      "urn:cspace:pahma.cspace.berkeley.edu:vocabularies:name(datecertainty):item:name(approximate)'approximate'" }))
      .toBe("Earliest and latest 1850 · approximate");
  });

  it("asks CollectionSpace as the user types, and saves on change", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: false, group: {} }),
      { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const w = mount(DateInput, { props: { modelValue: "" } });
    const input = w.find("input");
    await input.setValue("the twenties");
    await input.trigger("input");
    expect(w.text()).toContain("Checking the date");
    await vi.advanceTimersByTimeAsync(350);
    await flushPromises();
    expect(fetchMock).toHaveBeenCalledWith("/api/dates/parse?text=the%20twenties", expect.anything());
    expect(w.text()).toContain("Can't interpret this date");
    await input.trigger("change");
    expect(w.emitted("update:modelValue")?.[0]).toEqual(["the twenties"]);
  });

  it("shows the stored parse without asking again", () => {
    const w = mount(DateInput, { props: { modelValue: "1920s", parsed: { value: "1920s", ok: true,
      group: { dateEarliestSingleYear: "1920", dateLatestYear: "1929" } } } });
    expect(w.text()).toContain("Earliest 1920 · latest 1929");
  });
});
