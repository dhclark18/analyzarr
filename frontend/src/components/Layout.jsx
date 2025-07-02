import React, { useState, useEffect } from 'react';
import { Container, Row, Col, Navbar, Nav } from 'react-bootstrap';
import { Link } from 'react-router-dom';
import './Layout.css';

export default function Layout({ children }) {
  const [stats, setStats] = useState({
    totalEpisodes: 0,
    totalShows: 0,
    totalMismatches: 0,
    totalMissingTitles: 0
  });

  useEffect(() => {
    fetch('/api/stats')
      .then(res => res.ok ? res.json() : Promise.reject(res.statusText))
      .then(data => setStats(data))
      .catch(err => console.error('Failed to load stats:', err));
  }, []);

  return (
    <>
      {/* Top‐level stats bar */}
      <Navbar bg="dark" variant="dark" className="mb-0">
        <Container fluid>
          <Navbar.Brand>Analyzarr</Navbar.Brand>
          <Nav className="ms-auto">
            <Nav.Item className="text-light me-3">
              Episodes: {stats.totalEpisodes}
            </Nav.Item>
            <Nav.Item className="text-light me-3">
              Shows: {stats.totalShows}
            </Nav.Item>
            <Nav.Item className="text-light me-3">
              Mismatches: {stats.totalMismatches}
            </Nav.Item>
            <Nav.Item className="text-light">
              Missing Titles: {stats.totalMissingTitles}
            </Nav.Item>
          </Nav>
        </Container>
      </Navbar>

      {/* Secondary site‐nav bar */}
      <Navbar bg="dark" variant="dark" className="navbar-secondary mb-3">
        <Container fluid>
          <Nav>
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
        </Container>
      </Navbar>

      <Container fluid>
        <Row>
          <Col xs="auto" className="sidebar p-0">
            <Nav className="flex-column bg-dark vh-100">
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
          <Col className="main-content p-3">
            {children}
          </Col>
        </Row>
      </Container>
    </>
  );
}
