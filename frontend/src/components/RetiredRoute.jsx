import React from 'react'
import { Link, useParams, useLocation } from 'react-router-dom'
import { MapPinOff, ArrowLeft } from 'lucide-react'
import PageLayout from './PageLayout'
import {
  resolveRoutePath,
  hiddenReasonFor,
} from '../constants/hiddenRoutes'

/**
 * Rendered in place of a retired route.
 *
 * Deliberately *not* a 404 and *not* a blank page. A 404 implies the URL was
 * wrong, which is false - the URL is the one the app used to hand out. A
 * blank shell implies the feature is still there and currently empty, which
 * is the same silent-sickness shape as every other "unmeasured value shown
 * as a measured one" in this app.
 *
 * This says the feature is gone, says why, and gives a route back. The
 * reason is quoted from the registry so the explanation and the hiding
 * decision cannot drift apart.
 */
export default function RetiredRoute() {
  const params = useParams()
  // The real pathname, so the reason is looked up the same way for every
  // retired route rather than being hardcoded for the one that exists
  // today. Adding a second entry to the registry needs no change here.
  const { pathname } = useLocation()
  const entry = hiddenReasonFor(pathname)

  // Should be unreachable: this component is only ever routed for a path the
  // registry knows about. Guarded anyway, because "the registry and the
  // router disagree" must render an explanation rather than a blank page -
  // a thrown error here would be caught by ErrorBoundary and reported as a
  // crash, sending someone to look for a bug in the app instead.
  if (!entry) {
    return (
      <PageLayout title="Unavailable" subtitle="Retired">
        <div className="max-w-2xl bg-surface-1 rounded-2xl border border-line p-8">
          <p className="text-sm text-ink-2">
            This page has been retired. It is not listed in the retired-routes
            registry, which means the router and the registry have drifted
            apart - worth reporting.
          </p>
          <Link
            to="/cases"
            className="inline-flex items-center gap-2 mt-5
                       text-sm font-semibold text-accent hover:underline">
            <ArrowLeft size={15} />
            Back to cases
          </Link>
        </div>
      </PageLayout>
    )
  }

  const alternative = entry.alternative
    ? {
        ...entry.alternative,
        to: resolveRoutePath(entry.alternative.to, params),
      }
    : null

  return (
    <PageLayout
      title={entry.label}
      subtitle="Retired"
    >
      <div className="max-w-2xl">
        <div className="bg-surface-1 rounded-2xl border border-line p-8">
          <div className="flex items-start gap-4">
            <MapPinOff
              size={28}
              className="text-ink-2 shrink-0 mt-0.5"
            />
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-ink-0">
                {entry.label} has been turned off
              </h2>
              <p className="text-sm text-ink-2 mt-2 leading-relaxed">
                {entry.reason}
              </p>

              {alternative && (
                <Link
                  to={alternative.to}
                  className="inline-flex items-center gap-2 mt-5
                             text-sm font-semibold text-accent
                             hover:underline">
                  <ArrowLeft size={15} />
                  {alternative.label}
                </Link>
              )}
            </div>
          </div>
        </div>
      </div>
    </PageLayout>
  )
}
