"use client";
// /items/{id} (B11).
import { use } from "react";

import { GatedPage } from "@/components/layout/page";
import { ModuleDetail } from "@/modules/_template/components/module-detail";
import { itemsConfig } from "@/modules/_template/config";

export default function ItemPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <GatedPage perm={itemsConfig.permissions.read}>
      {() => <ModuleDetail config={itemsConfig} id={id} />}
    </GatedPage>
  );
}
