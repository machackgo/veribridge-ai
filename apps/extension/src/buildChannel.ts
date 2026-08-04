// Build channel flag — substituted by esbuild at bundle time.
//
// `npm run build:release` defines __VB_DEV_BUILD__=false, producing the
// Chrome Web Store package: localhost app origins are untrusted and evidence
// may only be uploaded to the production API. Every other build (npm run
// build, npm run dev, the test bundler) leaves the flag undefined and runs as
// a dev-channel build so local development keeps working unchanged.

declare const __VB_DEV_BUILD__: boolean | undefined

export const IS_DEV_BUILD: boolean =
  typeof __VB_DEV_BUILD__ === "undefined" ? true : __VB_DEV_BUILD__
