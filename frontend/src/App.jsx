import React, { useEffect, useState } from 'react';
import {
  Container,
  Row,
  Col,
  Card,
  Button,
  Spinner,
  Alert
} from 'react-bootstrap';

import './App.css';
import { fetchSeries } from './api';

export default function App() {
  const [series, setSeries]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  useEffect(() => {
    fetchSeries()
      .then(data => setSeries(data))
      .catch(err  => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <Container className="app-container text-center">
      <Spinner animation="border" role="status" style={{ color: 'var(--color-primary)' }} />
    </Container>
  );

  if (error) return (
    <Container className="app-container">
      <Alert variant="danger">Error: {error}</Alert>
    </Container>
  );

  return (
    <Container className="app-container">
      <h1 className="page-title">My Sonarr Library</h1>
      <Row xs={1} sm={2} md={3} lg={4} className="g-3">
        {series.map(s => (
          <Col key={s.id}>
            <Card className="h-100 custom-card">
              <Card.Body className="d-flex flex-column">
                <Card.Title className="mb-2">{s.title}</Card.Title>
                <Card.Text className="text-muted mb-4">
                  {s.seasons.length} seasons
                </Card.Text>
                <div className="mt-auto">
                  <Button className="btn-primary-custom me-2">
                    View Seasons
                  </Button>
                  <Button className="btn-accent">
                    Refresh
                  </Button>
                </div>
              </Card.Body>
            </Card>
          </Col>
        ))}
      </Row>
    </Container>
  );
}

