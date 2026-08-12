import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchMe,
  loginUser,
  logoutUser,
  registerUser,
  type CredentialsPayload,
} from '@/lib/api'

export const ME_QUERY_KEY = ['me'] as const

/** 当前登录状态：/api/me 结果，401 视为未登录。 */
export function useMe() {
  return useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: fetchMe,
    retry: false,
    staleTime: 60 * 1000,
  })
}

export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: CredentialsPayload) => loginUser(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY }),
  })
}

export function useRegister() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: CredentialsPayload) => registerUser(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY }),
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: logoutUser,
    onSettled: () => queryClient.removeQueries({ queryKey: ME_QUERY_KEY }),
  })
}
