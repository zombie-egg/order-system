import { useCallback, useEffect, useState } from 'react';

export interface AsyncResource<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
  setData: React.Dispatch<React.SetStateAction<T | null>>;
}

export function useAsyncResource<T>(loader: () => Promise<T>): AsyncResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void loader().then(
      (value) => {
        if (active) {
          setData(value);
          setLoading(false);
        }
      },
      (reason: unknown) => {
        if (active) {
          setError(reason);
          setLoading(false);
        }
      },
    );
    return () => {
      active = false;
    };
  }, [loader, reloadToken]);

  const reload = useCallback(() => {
    setReloadToken((value) => value + 1);
  }, []);

  return { data, error, loading, reload, setData };
}
