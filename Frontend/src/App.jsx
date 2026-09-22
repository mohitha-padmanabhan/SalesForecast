import React from 'react';
import './App.css';
import AppRoutes from './routes/AppRoutes';

function App() {
  return (
    <div className="app">
      <div className="app-content">
        <AppRoutes />
      </div>
    </div>
  );
}

export default App;