"use client";

import { createContext, useContext } from "react";

export const DeveloperModeContext = createContext(false);
export const useDeveloperMode = () => useContext(DeveloperModeContext);
