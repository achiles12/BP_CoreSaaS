"use client";
// /items: the template module's list (B11). COPYING: change the import and perm.
import { GatedPage } from "@/components/layout/page";
import { ModuleList } from "@/modules/_template/components/module-list";
import { itemsConfig } from "@/modules/_template/config";

export default function ItemsPage() {
  return (
    <GatedPage perm={itemsConfig.permissions.read} wide>
      {() => <ModuleList config={itemsConfig} />}
    </GatedPage>
  );
}
