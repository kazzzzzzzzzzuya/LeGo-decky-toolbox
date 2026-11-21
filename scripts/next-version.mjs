// The next version after a release, by the project's rule:
//   x.y.z: z counts fixes up to 10; then y goes up (z back to 0), up to 20; then x (y and z back to 0).
//   x also goes up by hand for a major change.
// Prints the next version for package.json's (or the given) version.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export function nextVersion(v) {
  const [x, y, z] = String(v).split("-")[0].split(".").map((n) => parseInt(n, 10) || 0);
  if (z < 10) return `${x}.${y}.${z + 1}`;
  if (y < 20) return `${x}.${y + 1}.0`;
  return `${x + 1}.0.0`;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const current = process.argv[2] ?? JSON.parse(readFileSync("package.json", "utf8")).version;
  console.log(nextVersion(current));
}
