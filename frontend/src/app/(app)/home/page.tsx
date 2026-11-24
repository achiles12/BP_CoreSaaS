import { redirect } from "next/navigation";

// B08 had one landing page here. Since B09 every user has their own
// (/home/<role>, /platform): /post-login decides which (D4). proxy.ts
// already answers /home with a 307; this is the fallback.
export default function HomeRedirect() {
  redirect("/post-login");
}
