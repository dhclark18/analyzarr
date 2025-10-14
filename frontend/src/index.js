// src/index.js
import React from 'react';
import ReactDOM from 'react-dom/client';
import 'bootstrap/dist/css/bootstrap.min.css';
import { BrowserRouter, Routes, Route } from 'react-router-dom';

import App from './App';
import './components/Layout.css';
import SeriesDetail from './pages/SeriesDetail';
import EpisodeDetail from './pages/EpisodeDetails';
import Overview from './pages/Overview';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <BrowserRouter>
    <Routes>
      <Route path="/overview" element={<Overview />} />
      <Route path="/" element={<App />} />
      <Route path="/series/:seriesTitle" element={<SeriesDetail />} />
      <Route path="/episode/:key" element={<EpisodeDetail />} />
    </Routes>
  </BrowserRouter>
);
