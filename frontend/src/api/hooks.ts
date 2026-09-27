import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { notifications } from '@mantine/notifications'
import { useMemo } from 'react'
import { api, ApiError, request, unwrap, type Account, type Category, type Debt, type Earmark, type Project } from './client'

export const useAccounts = () =>
  useQuery({ queryKey: ['accounts'], queryFn: () => unwrap(api.GET('/api/v1/accounts')) })

export const useCategories = () =>
  useQuery({ queryKey: ['categories'], queryFn: () => unwrap(api.GET('/api/v1/categories')), staleTime: 60_000 })

export const useProjects = () => useQuery({ queryKey: ['projects'], queryFn: () => unwrap(api.GET('/api/v1/projects')) })
export const useDebts = () => useQuery({ queryKey: ['debts'], queryFn: () => unwrap(api.GET('/api/v1/debts')) })
export const useEarmarks = () => useQuery({ queryKey: ['earmarks'], queryFn: () => unwrap(api.GET('/api/v1/earmarks')) })
export const useAssets = () => useQuery({ queryKey: ['assets'], queryFn: () => unwrap(api.GET('/api/v1/assets')) })
export const useSecurities = () => useQuery({ queryKey: ['securities'], queryFn: () => unwrap(api.GET('/api/v1/securities')) })
export const useSettings = () =>
  useQuery({ queryKey: ['settings'], queryFn: () => request<Record<string, unknown>>('GET', '/api/v1/settings') })

export function useReport<T>(key: unknown[], url: string | null) {
  return useQuery({ queryKey: ['report', ...key], queryFn: () => request<T>('GET', url!), enabled: !!url })
}

/** Lookup maps for rendering names. */
export function useLookups() {
  const accounts = useAccounts().data
  const categories = useCategories().data
  const projects = useProjects().data
  const debts = useDebts().data
  const earmarks = useEarmarks().data
  return useMemo(() => {
    const byId = <T extends { id: number }>(xs?: T[]) => new Map((xs ?? []).map((x) => [x.id, x]))
    const cat = byId<Category>(categories)
    return {
      accounts: byId<Account>(accounts),
      categories: cat,
      projects: byId<Project>(projects),
      debts: byId<Debt>(debts),
      earmarks: byId<Earmark>(earmarks),
      categoryPath: (id?: number | null) => {
        if (!id) return ''
        const c = cat.get(id)
        if (!c) return `#${id}`
        const parent = c.parent_id ? cat.get(c.parent_id) : null
        return parent ? `${parent.name} › ${c.name}` : c.name
      },
    }
  }, [accounts, categories, projects, debts, earmarks])
}

export function notifyError(e: unknown) {
  const message = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e)
  notifications.show({ color: 'red', title: 'Error', message })
}

/** Mutation that shows errors and invalidates the given query keys on success. */
export function useApiMutation<TVars, TRes>(fn: (v: TVars) => Promise<TRes>, invalidate: unknown[][] = [], successMsg?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k }))
      if (successMsg) notifications.show({ color: 'teal', message: successMsg })
    },
    onError: notifyError,
  })
}

/** Everything that depends on ledger data. */
export const LEDGER_KEYS: unknown[][] = [['txns'], ['report'], ['accounts'], ['debts'], ['earmarks'], ['assets']]
