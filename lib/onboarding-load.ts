type LoadError = { status?: number; message?: string } | undefined;
type LoadState = {
  kind: "ready" | "warning" | "sign-in" | "unavailable" | "forbidden";
  title: string;
  message: string;
};

/** A missing workspace after a failed request does not establish an expired session. */
export function onboardingLoadState(
  hasSession: boolean,
  error: LoadError,
  role: "candidate" | "employer",
): LoadState {
  const subject = role === "candidate" ? "profile" : "organization";
  if (error?.status === 401 || (!error && !hasSession))
    return {
      kind: "sign-in",
      title: `Sign in to set up your ${subject}.`,
      message: `Sign in to securely save your ${subject}.`,
    };
  if (error?.status === 403)
    return {
      kind: "forbidden",
      title: "Your workspace access needs attention.",
      message:
        error.message ||
        `Your account does not have access to this ${subject} setup.`,
    };
  if (error && hasSession)
    return {
      kind: "warning",
      title: "Your latest information could not be refreshed.",
      message: "Your current edits are still here. Try again to reconnect.",
    };
  if (error)
    return {
      kind: "unavailable",
      title: `${role === "candidate" ? "Profile" : "Organization"} setup is temporarily unavailable.`,
      message:
        error.message ||
        "We could not load your saved information. Please try again.",
    };
  return { kind: "ready", title: "", message: "" };
}
