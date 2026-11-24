import { redirect } from "next/navigation";

// "/" has no page of its own (B08 D4). proxy.ts sends signed-out users on to /login.
export default function RootPage() {
  redirect("/home");
}
