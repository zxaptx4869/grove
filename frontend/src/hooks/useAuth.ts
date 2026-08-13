import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useGroveMutation } from '@/hooks/useGroveMutation'
import { queryKeys } from '@/lib/queryKeys'
import {
  fetchMe,
  loginUser,
  logoutUser,
  registerUser,
  type CredentialsPayload,
} from '@/lib/api'

/** 当前登录状态：/api/me 结果，401 视为未登录。 */
export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: fetchMe,
    retry: false,
    staleTime: 60 * 1000,
  })
}

export function useLogin() {
  return useGroveMutation({
    mutationFn: (payload: CredentialsPayload) => loginUser(payload),
    invalidates: [queryKeys.me],
  })
}

export function useRegister() {
  return useGroveMutation({
    mutationFn: (payload: CredentialsPayload) => registerUser(payload),
    invalidates: [queryKeys.me],
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  return useGroveMutation({
    mutationFn: logoutUser,
    onSettled: () => queryClient.removeQueries({ queryKey: queryKeys.me }),
  })
}
