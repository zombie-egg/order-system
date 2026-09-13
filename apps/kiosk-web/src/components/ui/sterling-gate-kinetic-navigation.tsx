import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { CustomEase } from 'gsap/CustomEase';
import { InfiniteGridBackdrop } from './the-infinite-grid';

if (typeof window !== 'undefined') {
  gsap.registerPlugin(CustomEase);
}

export interface KineticMenuItem {
  id: string;
  label: string;
  detail: string;
}

interface KineticNavigationProps {
  isOpen: boolean;
  items: KineticMenuItem[];
  language: 'zh-CN' | 'nl-NL';
  onClose: () => void;
  onSelect: (id: string) => void;
}

/**
 * Full-screen category navigation for the self-ordering kiosk.  It deliberately
 * has no routing dependency: a category choice is supplied back to the Kiosk
 * screen, which keeps the existing order and payment flow intact.
 */
export function SterlingGateKineticNavigation({
  isOpen,
  items,
  language,
  onClose,
  onSelect,
}: KineticNavigationProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!containerRef.current) return;
    try {
      if (!gsap.parseEase('sip-main')) {
        CustomEase.create('sip-main', '0.65, 0.01, 0.05, 0.99');
      }
    } catch {
      // The default GSAP easing remains available on older kiosk browsers.
    }
    const overlay = containerRef.current.querySelector('.kinetic-overlay');
    const panel = containerRef.current.querySelector('.kinetic-menu-panel');
    const links = containerRef.current.querySelectorAll('.kinetic-menu-item');
    const closeButton = containerRef.current.querySelector('.kinetic-close-button');

    const context = gsap.context(() => {
      const timeline = gsap.timeline({ defaults: { ease: 'sip-main' } });
      if (isOpen) {
        timeline
          .set(overlay, { display: 'block' })
          .set(panel, { xPercent: 0 })
          .fromTo(overlay, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.2 })
          .fromTo(
            links,
            { yPercent: 135, rotation: 7 },
            { yPercent: 0, rotation: 0, stagger: 0.055, duration: 0.65 },
            '<+=0.25',
          )
          .fromTo(closeButton, { autoAlpha: 0, y: -14 }, { autoAlpha: 1, y: 0, duration: 0.35 }, '<');
      } else {
        timeline
          .to(overlay, { autoAlpha: 0, duration: 0.22 })
          .set(overlay, { display: 'none' });
      }
    }, containerRef);

    return () => context.revert();
  }, [isOpen]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isOpen) onClose();
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [isOpen, onClose]);

  return (
    <div ref={containerRef} className="kinetic-navigation">
      <div className="kinetic-overlay" aria-hidden={!isOpen}>
        <button
          className="kinetic-scrim"
          type="button"
          aria-label={language === 'zh-CN' ? '关闭菜单' : 'Menu sluiten'}
          onClick={onClose}
        />
        <section className="kinetic-menu-panel" aria-label={language === 'zh-CN' ? '选择饮品分类' : 'Drankcategorie kiezen'}>
          <InfiniteGridBackdrop idPrefix="kiosk-menu-grid" />

          <header className="kinetic-menu-header">
            <div className="kinetic-brand">SIP PILOT <span>· {language === 'zh-CN' ? '自助点单' : 'ZELFBESTELLEN'}</span></div>
            <div className="kinetic-header-actions">
              <span className="kinetic-menu-prompt">{language === 'zh-CN' ? '点这里' : 'klik hier'}</span>
              <button className="kinetic-close-button" type="button" onClick={onClose}>
                {language === 'zh-CN' ? '关闭' : 'Sluiten'} <b aria-hidden="true">×</b>
              </button>
            </div>
          </header>

          <div className="kinetic-menu-content">
            <p className="kinetic-kicker">{language === 'zh-CN' ? '今天想喝点什么？' : 'WAT WIL JE VANDAAG DRINKEN?'}</p>
            <ul className="kinetic-menu-list">
              {items.map((item, index) => (
                <li
                  className="kinetic-menu-item"
                  data-shape={(index % 3) + 1}
                  key={item.id}
                >
                  <button type="button" onClick={() => onSelect(item.id)}>
                    <span className="kinetic-menu-index">0{index + 1}</span>
                    <span className="kinetic-menu-label">{item.label}</span>
                    <span className="kinetic-menu-detail">{item.detail}</span>
                    <span className="kinetic-menu-arrow" aria-hidden="true">↗</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>
    </div>
  );
}
