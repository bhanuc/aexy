import { describe, it, expect } from "vitest";

import {
  hasUnmatchableDomains,
  isValidDomainTag,
  normalizeDomainTag,
  splitStoredDomainValue,
  splitStoredDomains,
} from "@/lib/domain-tags";

/**
 * Master Data's domain rows decide which account a ticket belongs to and who it
 * lands on. A row that cannot match is not an error anybody sees — mail from
 * that partner just routes as if the row were absent — so the parsing is worth
 * pinning down directly.
 *
 * The three real values at the bottom are the ones that were actually found in
 * the Bimaplan workspace, saved through a field that split on commas while its
 * own placeholder demonstrated slashes.
 */

describe("normalizeDomainTag", () => {
  it("lower-cases, because sender matching compares lower-cased", () => {
    expect(normalizeDomainTag("ACME.com")).toBe("acme.com");
    expect(normalizeDomainTag("Bob@Acme.COM")).toBe("bob@acme.com");
  });

  it("removes every space, not just the ends", () => {
    expect(normalizeDomainTag("  acme.com  ")).toBe("acme.com");
    expect(normalizeDomainTag("acme .com")).toBe("acme.com");
    expect(normalizeDomainTag("bob @ acme.com")).toBe("bob@acme.com");
    expect(normalizeDomainTag("\tacme.com\n")).toBe("acme.com");
  });

  it("strips what a mail client puts on the clipboard", () => {
    expect(normalizeDomainTag("mailto:bob@acme.com")).toBe("bob@acme.com");
    expect(normalizeDomainTag("<bob@acme.com>")).toBe("bob@acme.com");
    expect(normalizeDomainTag('"bob@acme.com"')).toBe("bob@acme.com");
    expect(normalizeDomainTag("(acme.com)")).toBe("acme.com");
  });

  it("strips a leading @, which is how people write a whole domain", () => {
    expect(normalizeDomainTag("@acme.com")).toBe("acme.com");
  });

  it("keeps an address's own @", () => {
    expect(normalizeDomainTag("bob@acme.com")).toBe("bob@acme.com");
  });

  it("strips the dots and commas a trailing separator leaves behind", () => {
    expect(normalizeDomainTag("acme.com.")).toBe("acme.com");
    expect(normalizeDomainTag("acme.com,")).toBe("acme.com");
    expect(normalizeDomainTag(".acme.com")).toBe("acme.com");
  });

  it("drops a token with nothing left in it", () => {
    expect(normalizeDomainTag("   ")).toBe("");
    expect(normalizeDomainTag("...")).toBe("");
    expect(normalizeDomainTag("/")).toBe("");
  });
});

describe("isValidDomainTag", () => {
  it("accepts hostnames and addresses", () => {
    expect(isValidDomainTag("acme.com")).toBe(true);
    expect(isValidDomainTag("mail.acme.co.uk")).toBe(true);
    expect(isValidDomainTag("my-partner.in")).toBe(true);
    expect(isValidDomainTag("bob@acme.com")).toBe(true);
    expect(isValidDomainTag("bob+claims@acme.com")).toBe(true);
  });

  it("rejects a value with no dot — a typo that would match nothing", () => {
    expect(isValidDomainTag("acme")).toBe(false);
    expect(isValidDomainTag("bob@localhost")).toBe(false);
  });

  it("rejects leftovers that are not addresses at all", () => {
    expect(isValidDomainTag("")).toBe(false);
    expect(isValidDomainTag("acme .com")).toBe(false);
    expect(isValidDomainTag("-acme.com")).toBe(false);
    expect(isValidDomainTag("acme..com")).toBe(false);
    expect(isValidDomainTag("a@b@acme.com")).toBe(false);
  });
});

describe("splitStoredDomainValue", () => {
  it("splits on every separator a person might reach for", () => {
    expect(splitStoredDomainValue("a.com, b.com")).toEqual(["a.com", "b.com"]);
    expect(splitStoredDomainValue("a.com; b.com")).toEqual(["a.com", "b.com"]);
    expect(splitStoredDomainValue("a.com / b.com")).toEqual(["a.com", "b.com"]);
    expect(splitStoredDomainValue("a.com | b.com")).toEqual(["a.com", "b.com"]);
    expect(splitStoredDomainValue("a.com b.com")).toEqual(["a.com", "b.com"]);
    expect(splitStoredDomainValue("a.com\nb.com")).toEqual(["a.com", "b.com"]);
  });

  it("leaves an already-clean value alone", () => {
    expect(splitStoredDomainValue("zingbus.com")).toEqual(["zingbus.com"]);
  });

  it("de-duplicates rather than producing two identical chips", () => {
    expect(splitStoredDomainValue("a.com, A.COM")).toEqual(["a.com"]);
  });

  it("handles a list pasted out of a mail client", () => {
    expect(splitStoredDomainValue('"Bob" <bob@acme.com>, carol@acme.com')).toEqual([
      "bob",
      "bob@acme.com",
      "carol@acme.com",
    ]);
  });
});

describe("the rows actually found in the Bimaplan workspace", () => {
  it("recovers Delovita's three addresses", () => {
    expect(splitStoredDomains(["pankaj.goyal@heyev.co / bhavya@heyev.co / gj@heyev.co"])).toEqual([
      "pankaj.goyal@heyev.co",
      "bhavya@heyev.co",
      "gj@heyev.co",
    ]);
  });

  it("recovers JLL's mixed address and domain", () => {
    expect(splitStoredDomains(["grouphealthsupport@magmainsurance.com / morganstanley.com"])).toEqual([
      "grouphealthsupport@magmainsurance.com",
      "morganstanley.com",
    ]);
  });

  it("recovers Slikk's two domains", () => {
    expect(splitStoredDomains(["slikk.club / getplaced.in"])).toEqual([
      "slikk.club",
      "getplaced.in",
    ]);
  });

  it("flags exactly the rows that need repair and no others", () => {
    expect(hasUnmatchableDomains(["slikk.club / getplaced.in"])).toBe(true);
    expect(hasUnmatchableDomains(["acme"])).toBe(true);
    // A healthy row must not be flagged, or the warning becomes noise on all 55.
    expect(hasUnmatchableDomains(["zingbus.com"])).toBe(false);
    expect(hasUnmatchableDomains(["agrosperity.com", "bob@acme.com"])).toBe(false);
    // No domains at all is a different warning, not a repair.
    expect(hasUnmatchableDomains([])).toBe(false);
  });
});
