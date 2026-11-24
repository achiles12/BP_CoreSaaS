"use client";
// S05: a signed-in user without an organization (B04 D15: landing_path null).
// Users with an org are sent to their own landing page.
import { Building2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { useSession, useSignOut } from "@/lib/auth";

export default function NoOrganizationPage() {
  const { me } = useSession();
  const router = useRouter();
  const signOut = useSignOut();
  useEffect(() => {
    if (me?.landing_path) router.replace(me.landing_path);
  }, [me, router]);
  if (!me || me.landing_path) return null;
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 py-16 text-center">
      <Building2 className="text-muted-foreground size-10" aria-hidden />
      <h1 className="text-2xl font-semibold">You are not a member of an organization</h1>
      <p className="text-muted-foreground text-sm">
        Your account ({me.user.email}) is not part of any organization yet. Ask an organization
        administrator to send you an invitation, then open the link in the email.
      </p>
      <Button variant="outline" onClick={() => void signOut()}>
        Log out
      </Button>
    </div>
  );
}
