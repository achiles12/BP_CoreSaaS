// Client-side highlighting of search terms (B10 D7; review focus 3).
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Highlight } from "./highlight";

function marks(container: HTMLElement) {
  return Array.from(container.querySelectorAll("mark")).map((m) => m.textContent);
}

describe("Highlight", () => {
  it("marks every query word, case-insensitively", () => {
    const { container } = render(
      <Highlight text="Quarterly Report and quarterly plan" query="quarterly plan" />,
    );
    expect(marks(container)).toEqual(["Quarterly", "quarterly", "plan"]);
    expect(container.textContent).toBe("Quarterly Report and quarterly plan");
  });

  it("treats regex characters literally", () => {
    const { container } = render(<Highlight text="see a.b( here and aXb" query="a.b(" />);
    expect(marks(container)).toEqual(["a.b("]);
  });

  it("renders HTML in the text as text", () => {
    const { container } = render(<Highlight text="<b>bold</b> x" query="bold" />);
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toBe("<b>bold</b> x");
  });

  it("empty query or text renders the text unchanged", () => {
    const { container } = render(<Highlight text="plain" query="  " />);
    expect(marks(container)).toEqual([]);
    expect(container.textContent).toBe("plain");
  });
});
