"use client";
// /items/new (B11).
import { GatedPage } from "@/components/layout/page";
import { ModuleForm } from "@/modules/_template/components/module-form";
import { itemsConfig } from "@/modules/_template/config";

export default function NewItemPage() {
  return (
    <GatedPage perm={itemsConfig.permissions.write}>
      {() => <ModuleForm config={itemsConfig} mode="create" />}
    </GatedPage>
  );
}
