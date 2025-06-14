import React, { useEffect, useState } from 'react';
import { Container, Row, Col, Card, Button, Spinner, Alert, Badge } from 'react-bootstrap';
import './App.css';
import { fetchSeries, fetchMismatchCounts } from './api';
import Layout from './components/Layout';
import { useNavigate } from 'react-router-dom';

export default function App() {
  const [series, setSeries]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  useEffect(() => {
    Promise.all([ fetchSeries(), fetchMismatchCounts() ])
      .then(([seriesData, mismatchData]) => {
        const lookup = mismatchData.reduce((acc, { seriesTitle, count }) => {
          acc[seriesTitle] = count;
          return acc;
        }, {});
        setSeries(
          seriesData.map(s => ({
            ...s,
            mismatchCount: lookup[s.title] || 0
          }))
        );
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <Container className="app-container text-center">
      <Spinner
        animation="border"
        role="status"
        style={{ color: 'var(--color-primary)' }}
      />
    </Container>
  );

  if (error) return (
    <Container className="app-container">
      <Alert variant="danger">Error: {error}</Alert>
    </Container>
  );

  return (
    <Layout>
      <Container fluid className="app-container">
        <h1 className="page-title">My Sonarr Library</h1>
        <Row xs={1} sm={2} md={3} lg={4} className="g-3">
          {series.map(s => (
            <Col key={s.id}>
              <Card className="h-100 custom-card">
                <Card.Body className="d-flex flex-column">
                  <Card.Title className="series-name">
                    {s.title}
                  </Card.Title>
                  <div className="mb-3">
                    <small className="seasons-text me-3">
                      {s.seasons.length} seasons
                    </small>
                    <Badge bg={s.mismatchCount === 0 ? 'success' : 'danger'}>
                      {s.mismatchCount} mismatch{s.mismatchCount !== 1 && 'es'}
                    </Badge>
                  </div>
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
    </Layout>
  );
}

