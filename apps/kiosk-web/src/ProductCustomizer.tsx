import { useEffect, useMemo, useRef, useState } from 'react';
import { allergenNames, formatMoney } from './format';
import type { CatalogOptionGroup, CatalogProduct } from './types';

interface ProductCustomizerProps {
  product: CatalogProduct;
  locale: string;
  language: 'zh-CN' | 'nl-NL';
  onCancel: () => void;
  onAdd: (optionValueIds: string[]) => void;
}

function initialSelections(product: CatalogProduct): Record<string, string[]> {
  return Object.fromEntries(product.option_groups.map((group) => [group.id, []]));
}

function groupError(
  group: CatalogOptionGroup,
  selections: string[],
  language: 'zh-CN' | 'nl-NL',
): string | null {
  if (selections.length < group.minimum_selections) {
    if (language === 'zh-CN') {
      return group.minimum_selections === 1
        ? `请选择 ${group.name}。`
        : `请至少选择 ${group.minimum_selections} 项 ${group.name}。`;
    }
    return group.minimum_selections === 1
      ? `Kies één optie voor ${group.name}.`
      : `Kies minimaal ${group.minimum_selections} opties voor ${group.name}.`;
  }
  if (selections.length > group.maximum_selections) {
    return language === 'zh-CN'
      ? `${group.name} 最多可选择 ${group.maximum_selections} 项。`
      : `Kies maximaal ${group.maximum_selections} opties voor ${group.name}.`;
  }
  return null;
}

export function ProductCustomizer(props: ProductCustomizerProps) {
  const { product, locale, language, onAdd, onCancel } = props;
  const [selections, setSelections] = useState(() => initialSelections(product));
  const [showErrors, setShowErrors] = useState(false);
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const allergens = allergenNames(product.allergen_data);
  const errors = product.option_groups
    .map((group) => groupError(group, selections[group.id] ?? [], language))
    .filter((error): error is string => error !== null);
  const selectedIds = Object.values(selections).flat();
  const selectedDelta = useMemo(
    () =>
      product.option_groups
        .flatMap((group) => group.values)
        .filter((value) => selectedIds.includes(value.id))
        .reduce((total, value) => total + value.price_delta_minor, 0),
    [product.option_groups, selectedIds],
  );

  useEffect(() => {
    closeButtonRef.current?.focus();

    function handleDialogKeys(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== 'Tab' || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), [tabindex]:not([tabindex="-1"])',
        ),
      );
      const first = focusable.at(0);
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    window.addEventListener('keydown', handleDialogKeys);
    return () => window.removeEventListener('keydown', handleDialogKeys);
  }, [onCancel]);

  function toggle(group: CatalogOptionGroup, valueId: string) {
    setSelections((current) => {
      const selected = current[group.id] ?? [];
      if (group.maximum_selections === 1) {
        return { ...current, [group.id]: selected.includes(valueId) ? [] : [valueId] };
      }
      return {
        ...current,
        [group.id]: selected.includes(valueId)
          ? selected.filter((id) => id !== valueId)
          : [...selected, valueId],
      };
    });
  }

  function addProduct() {
    if (errors.length > 0) {
      setShowErrors(true);
      return;
    }
    onAdd(selectedIds);
  }

  return (
    <div
      className="dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <section
        ref={dialogRef}
        className="product-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="customizer-title"
      >
        <header className="dialog-header">
          <div>
            <p className="eyebrow">{language === 'zh-CN' ? '定制饮品' : 'Maak je keuze'}</p>
            <h2 id="customizer-title">{product.name}</h2>
          </div>
          <button
            ref={closeButtonRef}
            className="icon-button"
            type="button"
            onClick={onCancel}
            aria-label={language === 'zh-CN' ? '关闭' : 'Sluiten'}
          >
            ×
          </button>
        </header>

        {product.description && <p className="product-description">{product.description}</p>}
        {allergens.length > 0 && (
          <p className="allergen-note">
            <strong>{language === 'zh-CN' ? '过敏原：' : 'Allergenen:'}</strong> {allergens.join(', ')}
          </p>
        )}

        <div className="option-groups">
          {product.option_groups.map((group) => {
            const selected = selections[group.id] ?? [];
            const error = showErrors ? groupError(group, selected, language) : null;
            return (
              <fieldset
                className="option-group"
                key={group.id}
                aria-describedby={error ? `${group.id}-error` : undefined}
              >
                <legend>
                  {group.name}
                  <span>
                    {group.minimum_selections > 0
                      ? language === 'zh-CN' ? '必选' : 'Verplicht'
                      : language === 'zh-CN' ? '可选' : 'Optioneel'} · {language === 'zh-CN' ? '最多' : 'max.'}{' '}
                    {group.maximum_selections}
                  </span>
                </legend>
                <div className="option-list">
                  {group.values.map((value) => {
                    const checked = selected.includes(value.id);
                    return (
                      <label
                        className={`option-choice ${checked ? 'selected' : ''}`}
                        key={value.id}
                      >
                        <input
                          type={group.maximum_selections === 1 ? 'radio' : 'checkbox'}
                          name={`group-${group.id}`}
                          checked={checked}
                          onChange={() => toggle(group, value.id)}
                        />
                        <span>{value.name}</span>
                        <small>
                          {value.price_delta_minor === 0
                            ? language === 'zh-CN' ? '已包含' : 'Inbegrepen'
                            : `+ ${formatMoney(value.price_delta_minor, product.currency, locale)}`}
                        </small>
                      </label>
                    );
                  })}
                </div>
                {error && (
                  <p className="field-error" id={`${group.id}-error`} role="alert">
                    {error}
                  </p>
                )}
              </fieldset>
            );
          })}
        </div>

        <footer className="dialog-actions">
          <button className="secondary-button" type="button" onClick={onCancel}>
            {language === 'zh-CN' ? '取消' : 'Annuleren'}
          </button>
          <button className="primary-button" type="button" onClick={addProduct}>
            {language === 'zh-CN' ? '加入' : 'Toevoegen'} · {formatMoney(product.price_minor + selectedDelta, product.currency, locale)}
          </button>
        </footer>
      </section>
    </div>
  );
}
