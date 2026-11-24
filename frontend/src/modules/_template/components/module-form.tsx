"use client";
// Generic create / edit form (B11): fields and Zod schema come from the
// config; server 422 field errors are mapped back onto the fields.
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm, type Path } from "react-hook-form";
import { toast } from "sonner";

import { errorText } from "@/components/data/data-table";
import { FormAlert, FormField } from "@/components/forms/form-field";
import { PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { NativeSelect, Textarea } from "@/components/ui/native";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession } from "@/lib/auth";
import { applyServerErrors } from "@/lib/forms";
import { tenantRequest } from "@/lib/tenant";

import type { AnyModuleConfig } from "../types";

type Values = Record<string, string>;

function FormBody({
  config,
  initial,
  onSave,
  cancelHref,
}: {
  config: AnyModuleConfig;
  initial: Values;
  onSave: (v: Values) => Promise<void>;
  cancelHref: string;
}) {
  const [formError, setFormError] = useState<string | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(config.schema), defaultValues: initial });
  const { errors, isSubmitting } = form.formState;
  const names = config.fields.map((f) => f.name) as Path<Values>[];

  async function submit(v: Values) {
    setFormError(null);
    try {
      await onSave(v);
    } catch (err) {
      if (err instanceof NothingChanged) setFormError(err.message);
      else setFormError(applyServerErrors(err, form.setError, {}, names));
    }
  }

  return (
    <Card>
      <CardContent>
        <form noValidate onSubmit={form.handleSubmit(submit)} className="grid gap-4">
          <FormAlert message={formError} />
          {config.fields.map((f) => {
            const id = `field-${f.name}`;
            const error = errors[f.name]?.message as string | undefined;
            if (f.kind === "text") {
              return (
                <FormField
                  key={f.name}
                  id={id}
                  label={f.label}
                  hint={f.hint}
                  error={error}
                  maxLength={f.maxLength}
                  {...form.register(f.name)}
                />
              );
            }
            return (
              <div key={f.name} className="grid gap-2">
                <Label htmlFor={id}>{f.label}</Label>
                {f.kind === "textarea" ? (
                  <Textarea
                    id={id}
                    aria-invalid={error ? true : undefined}
                    maxLength={f.maxLength}
                    {...form.register(f.name)}
                  />
                ) : (
                  <NativeSelect
                    id={id}
                    aria-invalid={error ? true : undefined}
                    {...form.register(f.name)}
                  >
                    {f.options?.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </NativeSelect>
                )}
                {error && <p className="text-destructive text-xs">{error}</p>}
              </div>
            );
          })}
          <div className="flex gap-2">
            <Button type="submit" disabled={isSubmitting}>
              Save
            </Button>
            <Button variant="outline" asChild>
              <Link href={cancelHref}>Cancel</Link>
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

class NothingChanged extends Error {}

export function ModuleForm({
  config,
  mode,
  id,
}: {
  config: AnyModuleConfig;
  mode: "create" | "edit";
  id?: string;
}) {
  const { me } = useSession();
  const router = useRouter();
  const qc = useQueryClient();
  const req = me ? tenantRequest(me) : {};
  // The detail query is only needed for edit; an empty id keeps it idle.
  const existing = config.api.useGet(mode === "edit" ? (id ?? "") : "", req);
  if (!me) return null;

  async function afterSave(savedId: string, message: string) {
    toast.success(message);
    await qc.invalidateQueries({ queryKey: config.api.listKey });
    await qc.invalidateQueries({ queryKey: config.api.getKey(savedId) });
    router.push(`${config.basePath}/${savedId}`);
  }

  if (mode === "create") {
    return (
      <>
        <PageHeader title={`New ${config.label.toLowerCase()}`} />
        <FormBody
          config={config}
          initial={config.emptyValues}
          cancelHref={config.basePath}
          onSave={async (v) => {
            const created = await config.api.create(config.toCreate(v), req);
            await afterSave(created.id, `${config.label} created`);
          }}
        />
      </>
    );
  }

  if (existing.isError) {
    return (
      <p role="alert" className="text-destructive text-sm">
        {errorText(existing.error)}
      </p>
    );
  }
  if (existing.isPending) return <Skeleton className="h-64 w-full" />;
  const row = existing.data;
  return (
    <>
      <PageHeader title={`Edit ${config.label.toLowerCase()}`} />
      <FormBody
        config={config}
        initial={config.toValues(row)}
        cancelHref={`${config.basePath}/${row.id}`}
        onSave={async (v) => {
          const patch = config.toUpdate(v, row);
          if (Object.keys(patch).length === 0) throw new NothingChanged("Nothing changed.");
          await config.api.update(row.id, patch, req);
          await afterSave(row.id, `${config.label} saved`);
        }}
      />
    </>
  );
}
