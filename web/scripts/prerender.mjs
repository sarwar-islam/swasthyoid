// UX-3b: put the landing page's HTML into dist/index.html's #root (see src/prerender.tsx). Uses Vite's own SSR build.
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { build } from "vite";

await build({ logLevel: "warn", build: { ssr: "src/prerender.tsx", outDir: "dist-ssr", emptyOutDir: true } });
try {
  const { render } = await import(pathToFileURL("dist-ssr/prerender.js").href);
  const html = readFileSync("dist/index.html", "utf8");
  const marker = '<div id="root"></div>';
  if (!html.includes(marker)) throw new Error("dist/index.html has no empty #root");
  // Every other path gets the same file (SPA fallback), and a visitor may have chosen English or dark: then drop the
  // pre-rendered page before it paints and let the app render. Keep this script byte-identical: nginx's CSP pins its hash.
  const clear = `<script>try{if(location.pathname!=="/"||localStorage.getItem("swasthyoid.lang")==="en"||localStorage.getItem("swasthyoid.theme")==="dark")document.getElementById("root").innerHTML=""}catch(e){}</script>`;
  writeFileSync("dist/index.html", html.replace(marker, `<div id="root">${render()}</div>${clear}`));
  console.log("pre-rendered / into dist/index.html");
} finally {
  rmSync("dist-ssr", { recursive: true, force: true });
}
