"use client";
// /items/{id}/edit (B11).
import { use } from "react";

import { GatedPage } from "@/components/layout/page";
import { ModuleForm } from "@/modules/_template/components/module-form";
import { itemsConfig } from "@/modules/_template/config";

export default function EditItemPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <GatedPage perm={itemsConfig.permissions.write}>
      {() => <ModuleForm config={itemsConfig} mode="edit" id={id} />}
    </GatedPage>
  );
}
