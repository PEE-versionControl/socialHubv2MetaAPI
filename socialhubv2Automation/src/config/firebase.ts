import { initializeApp } from 'firebase/app';
import { getAuth } from 'firebase/auth';
import { initializeFirestore, memoryLocalCache } from 'firebase/firestore';

// Credentials come from .env.development (dev) or .env.production (prod).
// Vite loads the correct file automatically based on the mode.
// See .env.development.example and .env.production.example for the format.
const firebaseConfig = {
  apiKey:            import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain:        import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId:         import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket:     import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId:             import.meta.env.VITE_FIREBASE_APP_ID,
};

if (!firebaseConfig.projectId) {
  console.error(
    '[Firebase] Missing credentials. ' +
    'Create .env.development (for local dev) or .env.production (for prod) ' +
    'with the VITE_FIREBASE_* variables.'
  );
}

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
// memoryLocalCache avoids the IndexedDB persistence layer that triggers
// "INTERNAL ASSERTION FAILED: Unexpected state" in Firestore SDK v12+
// when writeBatch.commit() fires while an onSnapshot listener is active.
export const db = initializeFirestore(app, { localCache: memoryLocalCache() });
export const appId = firebaseConfig.projectId;