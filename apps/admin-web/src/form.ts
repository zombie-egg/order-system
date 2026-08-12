import type { FormEvent } from 'react';

export function formText(form: HTMLFormElement, name: string): string {
  const value = new FormData(form).get(name);
  return typeof value === 'string' ? value.trim() : '';
}

export function formNumber(form: HTMLFormElement, name: string): number {
  const value = Number(formText(form, name));
  if (!Number.isFinite(value)) {
    throw new Error(`${name} must be a number.`);
  }
  return value;
}

export function formChecked(form: HTMLFormElement, name: string): boolean {
  return new FormData(form).get(name) === 'on';
}

export type FormSubmit = (event: FormEvent<HTMLFormElement>) => void;
