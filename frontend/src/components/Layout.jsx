import React, { useState, useEffect } from 'react';
import { Container, Row, Col, Navbar, Nav } from 'react-bootstrap';
import { Link } from 'react-router-dom';
import './Layout.css';  // ensure this is imported

export default function Layout({ children }) {
  const [stats, setStats] = useState({
    totalEpisodes: 0,
    totalShows:    0,
    totalMismatches: 0,
    totalMissingTitles: 0
  });

  useEffect(() => {
    fetch('/api/stats')
      .then(res => res.ok ? res.json() : Promise.reject(res.statusText))
      .then(data => setStats(data))
      .catch(console.error);
  }, []);

  return (
    <>
      {/* Primary top‐level stats bar */}
      <Navbar expand="lg" className="navbar mb-0 shadow-sm">
        <Container fluid>
          <Navbar.Brand>Analyzarr</Navbar.Brand>
          <Nav className="ms-auto">
            <Nav.Item className="me-3">
              Episodes: {stats.totalEpisodes}
            </Nav.Item>
            <Nav.Item className="me-3">
              Shows: {stats.totalShows}
            </Nav.Item>
            <Nav.Item className="me-3">
              Mismatches: {stats.totalMismatches}
            </Nav.Item>
            <Nav.Item>
              Missing Titles: {stats.totalMissingTitles}
            </Nav.Item>
          </Nav>
        </Container>
      </Navbar>

      <Container fluid className="p-0">
        <Row className="g-0">
          {/* Sidebar */}
          <Col xs="auto" className="sidebar">
            <Nav className="flex-column pt-3">
              <Nav.Link as={Link} to="/overview" className="text-light">
                Overview
              </Nav.Link>
              <Nav.Link as={Link} to="/" className="text-light">
                Dashboard
              </Nav.Link>
              <Nav.Link as={Link} to="/settings" className="text-light">
                Settings
              </Nav.Link>
            </Nav>
          </Col>

          {/* Main content */}
          <Col className="main-col">
            {/* Secondary navbar now here, flush to sidebar */}
            <Navbar variant="dark" className="navbar-secondary mb-0 px-3">
              <Nav>
                stuff
              </Nav>
            </Navbar>

            <div className="main-content p-3">
              {children}
            </div>
          </Col>
        </Row>
      </Container>
    </>
  );
}
