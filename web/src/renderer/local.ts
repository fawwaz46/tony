/**
 * Entry for the local self-contained page.
 *
 * tony inlines the payload as a JSON script tag and this bundle as the page's
 * only script. Same renderReview as the hosted page — see render.ts.
 */
import { renderReview } from "./render";

const root = document.getElementById("tony-root");
const data = document.getElementById("tony-payload");
if (root && data) {
  renderReview(root, JSON.parse(data.textContent || "{}"));
}
