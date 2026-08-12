import { describe, expect, it } from 'vitest';
import { ApiRequestError, resolveLocalToken } from './api';

describe('resolveLocalToken', () => {
  it('prefers runtime config over stored session value and env', () => {
    expect(resolveLocalToken('cfg-token', 'stored-token', 'env-token')).toBe('cfg-token');
  });

  it('falls back to the stored session value when config is empty', () => {
    expect(resolveLocalToken('', 'stored-token', 'env-token')).toBe('stored-token');
  });

  it('falls back to the env value when config and storage are empty', () => {
    expect(resolveLocalToken(undefined, '', 'env-token')).toBe('env-token');
  });

  it('returns empty string when every source is missing', () => {
    expect(resolveLocalToken()).toBe('');
    expect(resolveLocalToken('', '', '')).toBe('');
    expect(resolveLocalToken(undefined, undefined, undefined)).toBe('');
  });

  it('treats empty strings as absent (empty-string fallback chain)', () => {
    expect(resolveLocalToken('', '', 'env-token')).toBe('env-token');
    expect(resolveLocalToken('cfg-token', '', '')).toBe('cfg-token');
  });
});

describe('ApiRequestError', () => {
  it('carries the HTTP status for gate detection', () => {
    const error = new ApiRequestError('API Request Failed: 401 Unauthorized', 401);
    expect(error).toBeInstanceOf(Error);
    expect(error.status).toBe(401);
    expect(error.message).toContain('401');
  });
});
