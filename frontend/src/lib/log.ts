// Tiny console logger (B08 D20). Everything is prefixed "[fe]" so frontend
// lines are easy to filter in the browser console. debug() is silent outside
// dev. Never pass request/response bodies here (they can hold passwords).
const isDev = (process.env.NEXT_PUBLIC_APP_ENV ?? "dev") === "dev";

type Fields = Record<string, unknown>;

export const log = {
  debug(msg: string, fields?: Fields) {
    if (isDev) console.debug(`[fe] ${msg}`, fields ?? "");
  },
  info(msg: string, fields?: Fields) {
    console.info(`[fe] ${msg}`, fields ?? "");
  },
  warn(msg: string, fields?: Fields) {
    console.warn(`[fe] ${msg}`, fields ?? "");
  },
  error(msg: string, fields?: Fields) {
    console.error(`[fe] ${msg}`, fields ?? "");
  },
};
