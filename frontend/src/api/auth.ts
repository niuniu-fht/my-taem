import request from './request'

export interface LoginParams {
  username: string
  password: string
}

export interface UserInfo {
  id: number
  username: string
  nickname: string
  is_active: boolean
  is_superuser: boolean
  created_at: string
}

export interface LoginResult {
  token: {
    access_token: string
    token_type: string
  }
  user: UserInfo
}

export function loginApi(data: LoginParams): Promise<LoginResult> {
  return request.post('/auth/login', data)
}

export function getMeApi(): Promise<UserInfo> {
  return request.get('/auth/me')
}
