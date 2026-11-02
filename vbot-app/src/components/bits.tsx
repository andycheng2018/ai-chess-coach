import { KIND_LABEL, VERIFICATION_LABEL, type CapabilityKind, type Verification } from '../domain/catalog';

export function KindChip({ kind }: { kind: CapabilityKind }) {
  return <span className={`chip kind-${kind}`}>{KIND_LABEL[kind]}</span>;
}

export function VerificationTag({ value }: { value: Verification }) {
  return <span className={`verify verify-${value}`}>{VERIFICATION_LABEL[value]}</span>;
}

export function ViewHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <header className="view-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="view-actions">{actions}</div>}
    </header>
  );
}
