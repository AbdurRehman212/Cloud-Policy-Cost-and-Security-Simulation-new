import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { driver } from 'driver.js';
import 'driver.js/dist/driver.css';
import { ROLE_RANK, TOUR_STEPS } from './steps';
import { readActive, readState, shouldAutoOffer, writeActive, writeState } from './storage';

const TourContext = createContext({ startTour: () => {}, tourActive: false });
export const useTour = () => useContext(TourContext);

const TARGET_TIMEOUT_MS = 6000;
const SIDEBAR_ANIMATION_MS = 350;

const selectorFor = (target) => `[data-tour="${target}"]`;

const waitForTarget = (target, needsContent) =>
  new Promise((resolve) => {
    const started = performance.now();
    const check = () => {
      const el = document.querySelector(selectorFor(target));
      const rect = el && el.getBoundingClientRect();
      if (el && rect.width > 0 && (!needsContent || rect.height > 24)) return resolve(el);
      if (performance.now() - started > TARGET_TIMEOUT_MS) return resolve(null);
      return setTimeout(check, 150);
    };
    check();
  });

const setSidebar = (open) => window.dispatchEvent(new CustomEvent('fyp-tour-sidebar', { detail: { open } }));

function WelcomeDialog({ onStart, onSkip }) {
  const startRef = useRef(null);
  useEffect(() => {
    startRef.current?.focus();
    const onKey = (e) => e.key === 'Escape' && onSkip();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onSkip]);

  return (
    <div className="fixed inset-0 z-[10001] flex items-center justify-center bg-black/50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-welcome-title"
        className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl dark:bg-gray-800"
      >
        <h2 id="tour-welcome-title" className="text-xl font-bold text-gray-900 dark:text-white">
          Welcome! Want a quick tour?
        </h2>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
          This simulator is a safe practice cloud. A 2-minute guided tour shows you each part, in plain language, and
          never changes your data. You can skip it now and replay it any time with <strong>Help / Take a Tour</strong>.
        </p>
        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" onClick={onSkip} className="btn-secondary justify-center" data-testid="tour-skip-welcome">
            Skip for now
          </button>
          <button type="button" ref={startRef} onClick={onStart} className="btn-primary justify-center" data-testid="tour-start">
            Start the tour
          </button>
        </div>
      </div>
    </div>
  );
}

export function TourProvider({ children }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const user = useSelector((state) => state.auth.user);
  const currentOrganization = useSelector((state) => state.organization.currentOrganization);
  const role = currentOrganization?.my_role || currentOrganization?.role || null;

  const [welcomeOpen, setWelcomeOpen] = useState(false);
  const [tourActive, setTourActive] = useState(false);

  const pathRef = useRef(pathname);
  const driverRef = useRef(null);
  const stepsRef = useRef([]);
  const runRef = useRef(0);
  const userIdRef = useRef(null);
  const roleRef = useRef(null);
  const pendingStartRef = useRef(null); // a start requested before the user/role finished loading
  const offeredRef = useRef(null);
  pathRef.current = pathname;
  userIdRef.current = user?.id ?? null;
  roleRef.current = role;

  const teardown = useCallback(() => {
    runRef.current += 1;
    const drv = driverRef.current;
    driverRef.current = null;
    if (drv) drv.destroy();
    setSidebar(false);
    setTourActive(false);
    writeActive(userIdRef.current, null);
  }, []);

  const finish = useCallback(
    (status) => {
      if (userIdRef.current) writeState(userIdRef.current, status);
      teardown();
    },
    [teardown],
  );

  const showStep = useCallback((index) => {
    const drv = driverRef.current;
    if (!drv) return;
    writeActive(userIdRef.current, index);
    drv.drive(index);
  }, []);

  // Moves to the step at `index`, navigating and waiting as needed. Steps whose target never
  // appears (role-restricted, empty state, feature not available) are skipped in the travel direction.
  const goTo = useCallback(
    async (index, direction = 1) => {
      const steps = stepsRef.current;
      const run = ++runRef.current;
      let i = index;
      while (i >= 0 && i < steps.length) {
        const step = steps[i];
        driverRef.current?.destroy();
        setSidebar(Boolean(step.sidebar));
        if (step.sidebar) await new Promise((r) => setTimeout(r, SIDEBAR_ANIMATION_MS));
        if (step.route && pathRef.current !== step.route) navigate(step.route);
        if (step.target) {
          const el = await waitForTarget(step.target, step.needsContent);
          if (run !== runRef.current) return; // a newer navigation request superseded this one
          if (el) {
            showStep(i);
            return;
          }
          i += direction; // unavailable control: skip it gracefully
        } else {
          if (step.route) await new Promise((r) => setTimeout(r, 250));
          if (run !== runRef.current) return;
          showStep(i);
          return;
        }
      }
      if (i >= steps.length) finish('completed');
      else goTo(0, 1);
    },
    [finish, navigate, showStep],
  );

  const startTour = useCallback(
    (fromIndex = 0) => {
      if (!userIdRef.current || !roleRef.current) {
        pendingStartRef.current = fromIndex; // e.g. Help clicked right after a reload: start once loaded
        return;
      }
      pendingStartRef.current = null;
      teardown();
      setWelcomeOpen(false);
      const rank = ROLE_RANK[role] ?? ROLE_RANK.member;
      const steps = TOUR_STEPS.filter((s) => !s.minRole || rank >= ROLE_RANK[s.minRole]);
      stepsRef.current = steps;
      const last = steps.length - 1;

      driverRef.current = driver({
        showProgress: true,
        progressText: 'Step {{current}} of {{total}}',
        nextBtnText: 'Next →',
        prevBtnText: '← Back',
        doneBtnText: 'End tour',
        closeBtnLabel: 'Skip tour',
        overlayClickBehavior: () => {}, // clicking outside must not end or advance the tour
        disableActiveInteraction: true, // the tour never clicks or submits anything for the user
        allowKeyboardControl: true,
        smoothScroll: true,
        stagePadding: 8,
        popoverClass: 'fyp-tour-popover',
        steps: steps.map((s) => ({
          element: s.target ? () => document.querySelector(selectorFor(s.target)) : undefined,
          data: { module: s.module },
          popover: { title: s.title, description: s.text, side: s.side || 'bottom', align: 'start' },
        })),
        onNextClick: (_el, _step, { state }) => goTo((state.activeIndex ?? 0) + 1, 1),
        onPrevClick: (_el, _step, { state }) => goTo((state.activeIndex ?? 0) - 1, -1),
        onDoneClick: () => finish('completed'),
        onDestroyed: (_el, _step, { reason }) => {
          if (reason === 'close' || reason === 'escape' || reason === 'overlay') finish('dismissed');
        },
        onPopoverRender: (popover, { state }) => {
          const module = state.activeStep?.data?.module;
          if (module) {
            const badge = document.createElement('div');
            badge.className = 'fyp-tour-module';
            badge.textContent = module;
            popover.title.parentElement.insertBefore(badge, popover.title);
          }
          const end = document.createElement('button');
          end.type = 'button';
          end.className = 'fyp-tour-end';
          end.textContent = 'Skip tour';
          end.setAttribute('data-testid', 'tour-end');
          end.onclick = () => finish(state.activeIndex === last ? 'completed' : 'dismissed');
          popover.footer.insertBefore(end, popover.footer.firstChild);
        },
      });
      setTourActive(true);
      goTo(Math.min(Math.max(fromIndex, 0), last), 1);
    },
    [finish, goTo, role, teardown],
  );

  // Offer the tour once to new accounts, or resume an in-progress tour after a page reload.
  useEffect(() => {
    if (!user?.id || !role) return;
    if (pendingStartRef.current !== null) {
      offeredRef.current = user.id; // they chose the tour themselves: do not also show the welcome dialog
      startTour(pendingStartRef.current);
      return;
    }
    if (offeredRef.current === user.id) return;
    offeredRef.current = user.id;
    const resumeAt = readActive(user.id);
    if (resumeAt !== null && !readState(user.id)) {
      startTour(resumeAt);
    } else if (shouldAutoOffer(user)) {
      setWelcomeOpen(true);
    }
  }, [user, role, startTour]);

  // Clean up on logout / unmount.
  useEffect(() => () => driverRef.current?.destroy(), []);

  const value = useMemo(() => ({ startTour, tourActive }), [startTour, tourActive]);

  return (
    <TourContext.Provider value={value}>
      {children}
      {welcomeOpen && (
        <WelcomeDialog
          onStart={() => startTour(0)}
          onSkip={() => {
            if (userIdRef.current) writeState(userIdRef.current, 'dismissed');
            setWelcomeOpen(false);
          }}
        />
      )}
    </TourContext.Provider>
  );
}
